"""Programa que o navegador abre no Windows só para subir o serviço."""

import json
import os
import socket
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST = "127.0.0.1"
NATIVE_NAME = "com.videoextensao.download"
MAX_MESSAGE = 1024 * 1024


def port_open(host: str, port: int) -> bool:
    sock = socket.socket()
    sock.settimeout(0.2)
    try:
        return sock.connect_ex((host, port)) == 0
    finally:
        sock.close()


def server_command() -> list[str]:
    scripts = ROOT / ".venv" / "Scripts"
    pythonw = scripts / "pythonw.exe"
    python = scripts / "python.exe"
    launcher = pythonw if pythonw.is_file() else python
    if not launcher.is_file():
        launcher = Path(sys.executable)
    return [str(launcher), "-m", "host"]


def _spawn(command: list[str], env: dict) -> None:
    # O navegador encerra este programa ao responder. O serviço precisa
    # continuar depois disso e se fechar sozinho quando o download acabar.
    kwargs = {
        "cwd": ROOT,
        "env": env,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if sys.platform != "win32":
        subprocess.Popen(command, start_new_session=True, **kwargs)
        return
    flags = (
        subprocess.DETACHED_PROCESS
        | subprocess.CREATE_NEW_PROCESS_GROUP
        | subprocess.CREATE_NO_WINDOW
        | subprocess.CREATE_BREAKAWAY_FROM_JOB
    )
    try:
        subprocess.Popen(command, creationflags=flags, **kwargs)
    except OSError:
        subprocess.Popen(
            command,
            creationflags=flags & ~subprocess.CREATE_BREAKAWAY_FROM_JOB,
            **kwargs,
        )


def start_server(port: int | None = None) -> bool:
    chosen = int(os.environ.get("MDE_PORT", "8734")) if port is None else port
    if port_open(HOST, chosen):
        return False
    env = os.environ.copy()
    env["MDE_IDLE_EXIT"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    _spawn(server_command(), env)
    return True


def _read_exact(stream, size: int) -> bytes:
    chunks = []
    remaining = size
    while remaining > 0:
        piece = stream.read(remaining)
        if not piece:
            return b""
        chunks.append(piece)
        remaining -= len(piece)
    return b"".join(chunks)


def read_message(stream) -> dict:
    raw = _read_exact(stream, 4)
    if len(raw) < 4:
        return {}
    length = struct.unpack("<I", raw)[0]
    if length <= 0 or length > MAX_MESSAGE:
        return {}
    data = _read_exact(stream, length)
    if len(data) < length:
        return {}
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def write_message(stream, payload: dict) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    stream.write(struct.pack("<I", len(body)))
    stream.write(body)
    stream.flush()


def main() -> None:
    ok = True
    started = False
    try:
        started = start_server()
    except Exception:
        ok = False
    try:
        read_message(sys.stdin.buffer)
    except Exception:
        pass
    try:
        write_message(sys.stdout.buffer, {"ok": ok, "started": started})
    except Exception:
        pass


if __name__ == "__main__":
    main()
