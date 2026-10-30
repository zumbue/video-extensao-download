"""Serviço HTTP em 127.0.0.1 para a extensão."""

import json
import os
import shutil
import socket
import socketserver
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from . import __version__
from .download import BusyError, DownloadManager, js_runtimes, probe_media, ytdlp_version
from .idle import IdleWatch
from .naming import UserError, detect_network, load_catalog, parse_request

CLIENT_HEADER = "video-extensao-download"
MAX_BODY = 32_768
HOST = "127.0.0.1"
EXTENSION_ROOT = Path(__file__).resolve().parents[1] / "extension"
STATIC_FILES = {
    "/": "popup.html",
    "/popup.html": "popup.html",
    "/popup.css": "popup.css",
    "/popup.js": "popup.js",
    "/detect.js": "detect.js",
    "/networks.json": "networks.json",
    "/icons/icon.svg": "icons/icon.svg",
    "/icons/icon16.png": "icons/icon16.png",
    "/icons/icon32.png": "icons/icon32.png",
    "/icons/icon48.png": "icons/icon48.png",
    "/icons/icon128.png": "icons/icon128.png",
}
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
}


def health_payload(idle: IdleWatch | None = None) -> dict:
    runtime = next(iter(js_runtimes()), None)
    enabled = idle is not None and idle.enabled
    return {
        "ok": True,
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "js_runtime": runtime,
        "ytdlp": ytdlp_version(),
        "version": __version__,
        "idle_exit": enabled,
        "idle_seconds": idle.idle_seconds if enabled else None,
        "settled_seconds": idle.settled_seconds if enabled else None,
    }


def keep_alive(path: str, busy: bool) -> str:
    if busy:
        return "pause"
    if path == "/health":
        return "skip"
    return "touch"


class App:
    def __init__(self, manager: DownloadManager, catalog: dict, probe=None, idle: IdleWatch | None = None):
        self.manager = manager
        self.catalog = catalog
        self.probe = probe or probe_media
        self.idle = idle


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args) -> None:
            path = urlparse(self.path).path
            if path == "/health" or path.startswith("/jobs/"):
                return
            if self.command == "GET":
                return
            print(f"[ved] {self.address_string()} {fmt % args}")

        def do_OPTIONS(self) -> None:
            self._send(204, b"")

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            self._activity(path)
            if path == "/health":
                self._send_json(200, health_payload(app.idle))
                return
            if path == "/downloads":
                if not self._post_allowed():
                    self._send_json(403, {"error": "Origem recusada."})
                    return
                self._send_json(200, app.manager.library())
                return
            if path.startswith("/jobs/"):
                job_id = path.removeprefix("/jobs/").strip("/")
                job = app.manager.get(job_id)
                if job is None:
                    self._send_json(404, {"error": "Download não encontrado."})
                    return
                self._send_json(200, job)
                return
            relative = STATIC_FILES.get(path)
            if relative is not None:
                self._send_static(relative)
                return
            self._send_json(404, {"error": "Caminho não encontrado."})

        def do_POST(self) -> None:
            if not self._post_allowed():
                self._send_json(403, {"error": "Origem recusada."})
                return
            path = urlparse(self.path).path
            self._activity(path)
            if path == "/download":
                self._download()
                return
            if path == "/probe":
                self._probe()
                return
            if path == "/folder":
                self._folder()
                return
            if path.startswith("/jobs/") and path.endswith("/cancel"):
                job_id = path.removeprefix("/jobs/").removesuffix("/cancel").strip("/")
                if not app.manager.cancel(job_id):
                    self._send_json(404, {"error": "Download não encontrado."})
                    return
                job = app.manager.get(job_id)
                self._send_json(200, job)
                return
            self._send_json(404, {"error": "Caminho não encontrado."})

        def _activity(self, path: str) -> None:
            idle = app.idle
            if idle is None:
                return
            kind = keep_alive(path, app.manager.busy())
            if kind == "pause":
                idle.pause()
            elif kind == "touch":
                idle.touch()

        def _local_origin(self) -> str:
            return f"http://127.0.0.1:{self.server.server_address[1]}"

        def _post_allowed(self) -> bool:
            origin = self.headers.get("Origin", "")
            if origin == "null":
                return False
            if origin.startswith(("http://", "https://")) and origin != self._local_origin():
                return False
            return self.headers.get("X-Mde-Client", "") == CLIENT_HEADER

        def _send_static(self, relative: str) -> None:
            path = EXTENSION_ROOT / relative
            if not path.is_file():
                self._send_json(404, {"error": "Caminho não encontrado."})
                return
            content_type = CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")
            self._send(200, path.read_bytes(), content_type)

        def _read_payload(self) -> dict | None:
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
            except ValueError:
                length = 0
            if length <= 0 or length > MAX_BODY:
                self._send_json(400, {"error": "Pedido inválido."})
                return None
            raw = self.rfile.read(length)
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError):
                self._send_json(400, {"error": "Pedido inválido."})
                return None
            if not isinstance(payload, dict):
                self._send_json(400, {"error": "Pedido inválido."})
                return None
            return payload

        def _folder(self) -> None:
            payload: dict = {}
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
            except ValueError:
                length = 0
            if length > 0:
                read = self._read_payload()
                if read is None:
                    return
                payload = read
            name = payload.get("name")
            if name is not None and not isinstance(name, str):
                self._send_json(400, {"error": "Arquivo inválido."})
                return
            try:
                app.manager.reveal(name)
            except OSError:
                self._send_json(500, {"error": "Não foi possível abrir a pasta."})
                return
            self._send_json(200, {"ok": True})

        def _download(self) -> None:
            payload = self._read_payload()
            if payload is None:
                return
            try:
                request = parse_request(payload, app.catalog)
            except UserError as exc:
                self._send_json(400, {"error": str(exc)})
                return
            try:
                job = app.manager.start(request)
            except UserError as exc:
                self._send_json(400, {"error": str(exc)})
                return
            except BusyError as exc:
                self._send_json(409, {"error": str(exc)})
                return
            self._send_json(202, job)

        def _probe(self) -> None:
            payload = self._read_payload()
            if payload is None:
                return
            url = payload.get("url")
            if not isinstance(url, str):
                self._send_json(400, {"error": "Informe o link."})
                return
            url = url.strip()
            if detect_network(url, app.catalog) is None:
                self._send_json(400, {"error": "Use um link http ou https."})
                return
            try:
                facts = app.probe(url)
            except Exception as exc:
                print(f"[ved] duração indisponível: {exc.__class__.__name__}: {str(exc)[:200]}")
                self._send_json(200, {"duration": None, "title": None})
                return
            if not isinstance(facts, dict):
                facts = {}
            duration = facts.get("duration")
            title = facts.get("title")
            if isinstance(duration, bool) or not isinstance(duration, (int, float)) or duration <= 0:
                duration = None
            else:
                duration = round(float(duration), 3)
            self._send_json(200, {
                "duration": duration,
                "title": title if isinstance(title, str) else None,
            })

        def _send_json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._send(status, body, "application/json; charset=utf-8")

        def _send(self, status: int, body: bytes, content_type: str = "text/plain; charset=utf-8") -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            origin = self.headers.get("Origin", "")
            local = f"http://127.0.0.1:{self.server.server_address[1]}"
            if origin.startswith(("chrome-extension://", "moz-extension://")) or origin == local:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Mde-Client")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Vary", "Origin")
            self.end_headers()
            self.wfile.write(body)

    return Handler


class ReuseServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


class InheritedServer(ReuseServer):
    daemon_threads = True

    def __init__(self, sock: socket.socket, handler) -> None:
        sock.setblocking(True)
        address = sock.getsockname()[:2]
        socketserver.BaseServer.__init__(self, address, handler)
        self.address_family = sock.family
        self.socket_type = sock.type
        self.socket = sock


def inherited_socket() -> socket.socket | None:
    try:
        count = int(os.environ.get("LISTEN_FDS", "0") or "0")
    except ValueError:
        return None
    if count < 1:
        return None
    expected = os.environ.get("LISTEN_PID")
    if expected and expected != str(os.getpid()):
        return None
    return socket.socket(fileno=3)


def serve(app: App, port: int, sock: socket.socket | None = None) -> ThreadingHTTPServer:
    if sock is not None:
        return InheritedServer(sock, make_handler(app))
    return ReuseServer((HOST, port), make_handler(app))


def _idle_seconds(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def main() -> None:
    port = int(os.environ.get("MDE_PORT", "8734"))
    downloads = Path(os.environ.get(
        "MDE_DOWNLOADS",
        Path.home() / "Downloads" / "Video Extensao Download",
    ))
    holder: dict = {}

    def on_idle() -> None:
        print("Serviço encerrado.")
        server = holder.get("server")
        if server is not None:
            server.shutdown()

    idle = IdleWatch(
        on_idle,
        idle_seconds=_idle_seconds("MDE_IDLE_SECONDS", 90),
        settled_seconds=_idle_seconds("MDE_SETTLED_SECONDS", 30),
        enabled=os.environ.get("MDE_IDLE_EXIT") == "1",
    )
    manager = DownloadManager(downloads, on_settled=idle.note_settled, on_start=idle.pause)
    idle.busy_check = manager.busy
    app = App(manager, load_catalog(), idle=idle)
    try:
        server = serve(app, port, inherited_socket())
    except OSError as exc:
        idle.stop()
        raise SystemExit(f"Não foi possível abrir a porta {port}: {exc}") from exc
    holder["server"] = server
    idle.touch()
    shown = server.server_address[1]
    print(f"Video Extensão Download em http://{HOST}:{shown}")
    print(f"Arquivos em {downloads}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServiço encerrado.")
    finally:
        idle.stop()
        server.server_close()
